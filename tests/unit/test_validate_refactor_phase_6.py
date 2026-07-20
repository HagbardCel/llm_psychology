"""Unit tests for the lean Phase 6 cutover validator."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_refactor_phase_6.py"
_SPEC = importlib.util.spec_from_file_location("validate_refactor_phase_6", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

make_targets = _MODULE.make_targets
validate = _MODULE.validate
validate_compose_model = _MODULE.validate_compose_model
validate_compose_config_file = _MODULE.validate_compose_config_file



def test_make_targets_detects_conventional_target() -> None:
    text = "finalization-check: prepare-runtime-dirs\n\t$(MAKE) lint\n"
    assert "finalization-check" in make_targets(text)


def test_make_targets_ignores_variable_assignment() -> None:
    text = "TARGET_SUPPORT_TESTS := \\\n\ttests/unit/foo.py\n"
    assert make_targets(text) == set()


def _valid_compose_model() -> dict:
    build = {
        "context": "/repo",
        "dockerfile": "Dockerfile",
        "target": "development",
    }
    health = {
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
    return {
        "services": {
            "api": {
                "build": build,
                "command": ["jung-api"],
                "entrypoint": None,
                "environment": {"JUNG_DATA_DIR": "/app/data/local"},
                "healthcheck": health,
                "ports": [
                    {
                        "host_ip": "127.0.0.1",
                        "published": "8000",
                        "target": 8000,
                    }
                ],
            },
            "api-usertest": {
                "build": build,
                "command": ["jung-api"],
                "entrypoint": None,
                "profiles": ["usertest-console"],
                "environment": {"JUNG_DATA_DIR": "/app/data/usertest"},
                "healthcheck": health,
                "ports": [
                    {
                        "host_ip": "127.0.0.1",
                        "published": "8001",
                        "target": 8000,
                    }
                ],
            },
        }
    }


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
