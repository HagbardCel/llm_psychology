"""Unit tests for the lean Phase 6 cutover validator."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_refactor_phase_6.py"
_SPEC = importlib.util.spec_from_file_location("validate_refactor_phase_6", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

Manifest = _MODULE.Manifest
ManifestItem = _MODULE.ManifestItem
REQUIRED_TEST_COMMAND = _MODULE.REQUIRED_TEST_COMMAND
make_targets = _MODULE.make_targets
supported_python_files = _MODULE.supported_python_files
validate = _MODULE.validate
validate_compose_config_file = _MODULE.validate_compose_config_file
validate_compose_model = _MODULE.validate_compose_model
validate_dockerfile = _MODULE.validate_dockerfile
validate_item_complete = _MODULE.validate_item_complete
validate_required_owner_closure = _MODULE.validate_required_owner_closure
validate_supported_imports = _MODULE.validate_supported_imports
validate_workflow = _MODULE.validate_workflow


def test_make_targets_detects_conventional_target() -> None:
    text = "finalization-check: prepare-runtime-dirs\n\t$(MAKE) lint\n"
    assert "finalization-check" in make_targets(text)


def test_make_targets_ignores_variable_assignment() -> None:
    text = "TARGET_SUPPORT_TESTS := \\\n\ttests/unit/foo.py\n"
    assert make_targets(text) == set()


def _build() -> dict[str, object]:
    return {
        "context": "/repo",
        "dockerfile": "Dockerfile",
        "target": "development",
    }


def _healthcheck() -> dict[str, object]:
    return {
        "test": [
            "CMD",
            "wget",
            "--no-verbose",
            "--tries=1",
            "-O",
            "/dev/null",
            "http://localhost:8000/api/v1/health",
        ]
    }


def _valid_test_service() -> dict[str, object]:
    return {
        "command": list(REQUIRED_TEST_COMMAND),
        "environment": {
            "PYTHONPATH": "/app/src",
            "PYTHONUNBUFFERED": "1",
        },
        "profiles": ["test"],
    }


def _valid_compose_model() -> dict:
    return {
        "services": {
            "api": {
                "build": _build(),
                "command": ["jung-api"],
                "entrypoint": None,
                "environment": {"JUNG_DATA_DIR": "/app/data/local"},
                "healthcheck": _healthcheck(),
                "ports": [
                    {
                        "host_ip": "127.0.0.1",
                        "published": "8000",
                        "target": 8000,
                    }
                ],
            },
            "api-usertest": {
                "build": _build(),
                "command": ["jung-api"],
                "entrypoint": None,
                "profiles": ["usertest-console"],
                "environment": {"JUNG_DATA_DIR": "/app/data/usertest"},
                "healthcheck": _healthcheck(),
                "ports": [
                    {
                        "host_ip": "127.0.0.1",
                        "published": "8001",
                        "target": 8000,
                    }
                ],
            },
            "test": _valid_test_service(),
        }
    }


def _item(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "kind": "filesystem",
        "path": "legacy/module.py",
        "action": "delete",
        "owner_pr": "6C",
        "status": "complete",
        "confidence": "confirmed",
        "responsibility": "example",
    }
    base.update(overrides)
    return base


def test_valid_compose_model_passes() -> None:
    assert validate_compose_model(_valid_compose_model()) == []


def test_missing_api_usertest_fails() -> None:
    model = _valid_compose_model()
    del model["services"]["api-usertest"]
    errors = validate_compose_model(model)
    assert any("api-usertest" in err for err in errors)


def test_wrong_command_fails() -> None:
    model = _valid_compose_model()
    model["services"]["api"]["command"] = ["python", "-m", "psychoanalyst_app.server"]
    errors = validate_compose_model(model)
    assert any("command" in err for err in errors)


def test_non_loopback_port_fails() -> None:
    model = _valid_compose_model()
    model["services"]["api"]["ports"][0]["host_ip"] = "0.0.0.0"
    errors = validate_compose_model(model)
    assert any("publish" in err for err in errors)


def test_equal_data_dirs_fail() -> None:
    model = _valid_compose_model()
    model["services"]["api-usertest"]["environment"]["JUNG_DATA_DIR"] = (
        "/app/data/local"
    )
    errors = validate_compose_model(model)
    assert any("must differ" in err or "usertest" in err for err in errors)


def test_legacy_console_service_fails() -> None:
    model = _valid_compose_model()
    model["services"]["console-ui"] = {"command": ["python"]}
    errors = validate_compose_model(model)
    assert any("console-ui" in err for err in errors)


def test_incorrect_health_endpoint_fails() -> None:
    model = _valid_compose_model()
    model["services"]["api"]["healthcheck"]["test"] = [
        "CMD",
        "wget",
        "http://localhost:8000/health",
    ]
    errors = validate_compose_model(model)
    assert any("healthcheck" in err for err in errors)


def test_test_service_env_file_fails() -> None:
    model = _valid_compose_model()
    model["services"]["test"]["env_file"] = [".env.test"]
    errors = validate_compose_model(model)
    assert any("env_file" in err for err in errors)


def test_test_service_legacy_environment_fails() -> None:
    model = _valid_compose_model()
    model["services"]["test"]["environment"]["APP_ENV"] = "testing"
    errors = validate_compose_model(model)
    assert any("legacy environment keys" in err for err in errors)


def test_test_service_incorrect_command_fails() -> None:
    model = _valid_compose_model()
    model["services"]["test"]["command"] = ["pytest", "tests/"]
    errors = validate_compose_model(model)
    assert any("services.test.command" in err for err in errors)


def test_missing_compose_config_file_fails(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    errors = validate_compose_config_file(missing)
    assert any("missing compose config" in err for err in errors)


def test_malformed_compose_config_fails(tmp_path: Path) -> None:
    bad = tmp_path / "compose.json"
    bad.write_text("{not-json", encoding="utf-8")
    errors = validate_compose_config_file(bad)
    assert any("malformed compose config" in err for err in errors)


def test_unknown_stage_fails(tmp_path: Path) -> None:
    errors = validate(tmp_path, stage="pre-cutover")
    assert errors == ["unknown stage: pre-cutover"]


@pytest.mark.parametrize(
    "published,target",
    [("8000", 8000), (8000, "8000"), ("8000", "8000")],
)
def test_port_scalar_normalization(published: object, target: object) -> None:
    model = _valid_compose_model()
    model["services"]["api"]["ports"][0]["published"] = published
    model["services"]["api"]["ports"][0]["target"] = target
    assert validate_compose_model(model) == []


def test_port_then_delete_without_replacement_rejected() -> None:
    with pytest.raises(ValidationError, match="requires replacements"):
        ManifestItem.model_validate(
            _item(action="port_then_delete", replacements=())
        )


def test_duplicate_manifest_kind_path_rejected() -> None:
    row = _item(path="legacy/dup.py")
    with pytest.raises(ValidationError, match="duplicate kind/path"):
        Manifest.model_validate(
            {
                "schema_version": 1,
                "status": "active",
                "items": [row, dict(row)],
            }
        )


def test_incomplete_6c_owner_fails_cutover() -> None:
    item = ManifestItem.model_validate(
        _item(status="in_progress", confidence="likely")
    )
    manifest = Manifest.model_validate(
        {
            "schema_version": 1,
            "status": "active",
            "items": [item.model_dump()],
        }
    )
    errors = validate_required_owner_closure(manifest, frozenset({"6C"}))
    assert any("owner_pr 6C" in err for err in errors)


def test_completed_delete_path_still_present_fails(tmp_path: Path) -> None:
    path = tmp_path / "legacy" / "gone.py"
    path.parent.mkdir()
    path.write_text("x = 1\n", encoding="utf-8")
    item = ManifestItem.model_validate(_item(path="legacy/gone.py"))
    errors = validate_item_complete(tmp_path, set(), item)
    assert any("still present" in err for err in errors)


def test_supported_import_of_psychoanalyst_app_fails(tmp_path: Path) -> None:
    supported = tmp_path / "tests" / "unit" / "jung"
    supported.mkdir(parents=True)
    (supported / "test_bad.py").write_text(
        "from psychoanalyst_app.config import Settings\n",
        encoding="utf-8",
    )
    for relative in _MODULE.SUPPORTED_TEST_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# ok\n", encoding="utf-8")
    for relative in _MODULE.SUPPORTED_TEST_ROOTS:
        root = tmp_path / relative
        root.mkdir(parents=True, exist_ok=True)
        if relative != Path("tests/unit/jung"):
            (root / "test_ok.py").write_text("x = 1\n", encoding="utf-8")
    errors = validate_supported_imports(tmp_path)
    assert any("psychoanalyst_app" in err for err in errors)


def test_missing_supported_file_fails(tmp_path: Path) -> None:
    files, errors = supported_python_files(tmp_path)
    assert files == []
    assert any("missing supported test file" in err for err in errors)
    assert any("missing supported test root" in err for err in errors)


def test_wrong_dockerfile_command_fails(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.11 AS development\nCMD [\"python\"]\n",
        encoding="utf-8",
    )
    errors = validate_dockerfile(tmp_path)
    assert any("CMD" in err for err in errors)


def test_workflow_without_finalization_check_fails(tmp_path: Path) -> None:
    path = tmp_path / ".github" / "workflows"
    path.mkdir(parents=True)
    (
        path / "release-candidate-validation.yml"
    ).write_text("name: rc\njobs: {}\n", encoding="utf-8")
    errors = validate_workflow(tmp_path)
    assert any("finalization-check" in err for err in errors)
