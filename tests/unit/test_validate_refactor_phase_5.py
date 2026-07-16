"""Unit tests for Phase 5 refactor validation."""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "validate_refactor_phase_5.py"
)
_SPEC = importlib.util.spec_from_file_location("validate_refactor_phase_5", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

RuntimeContract = _MODULE.RuntimeContract
extract_runtime_contract = _MODULE.extract_runtime_contract
validate_repository = _MODULE.validate_repository
validate_static_repository = _MODULE.validate_static_repository


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_validate_current_repository_passes() -> None:
    violations = validate_repository(_repo_root())
    assert violations == []


def test_extract_runtime_contract_does_not_invoke_runtime_factory() -> None:
    contract = extract_runtime_contract()
    assert contract.http_operations
    assert contract.websocket_paths == ("/api/v1/chat",)
    assert "send_message" in contract.command_discriminators
    assert "token" in contract.event_discriminators


def test_validate_static_missing_resilience_test_fails(tmp_path: Path) -> None:
    violations = validate_static_repository(tmp_path)
    messages = [item.message for item in violations]
    assert any("missing required test file" in message for message in messages)


def test_validate_static_legacy_ws_event_fails(tmp_path: Path) -> None:
    api_dir = tmp_path / "src/jung/api"
    api_dir.mkdir(parents=True)
    (api_dir / "bad.py").write_text(
        textwrap.dedent(
            """
            EVENT = "workflow_next_action"
            """
        ),
        encoding="utf-8",
    )
    violations = validate_static_repository(tmp_path)
    messages = [item.message for item in violations]
    assert any("legacy event" in message for message in messages)


def test_validate_runtime_contract_reports_missing_http_operation() -> None:
    contract = RuntimeContract(
        http_operations=frozenset(),
        websocket_paths=("/api/v1/chat",),
        command_discriminators=frozenset({"send_message"}),
        event_discriminators=_MODULE.EXPECTED_EVENT_DISCRIMINATORS,
        openapi_schemas={},
        ws_schemas={},
    )
    violations = _MODULE.validate_runtime_contract(contract)
    assert any("missing HTTP operation" in item.message for item in violations)
