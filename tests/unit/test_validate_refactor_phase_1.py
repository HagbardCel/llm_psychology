import importlib.util
import shutil
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "validate_refactor_phase_1.py"
)
_SPEC = importlib.util.spec_from_file_location("validate_refactor_phase_1", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
validate = _MODULE.validate
_direct_requirements = _MODULE._direct_requirements


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _copy_phase1_tree(target: Path) -> None:
    root = _repo_root()
    shutil.copytree(root / "docs", target / "docs")
    shutil.copytree(root / "tests/characterization", target / "tests/characterization")
    (target / "requirements.in").write_text("pydantic\n")
    (target / "requirements-dev.in").write_text("pytest\n")


def test_direct_requirements_excludes_comments_and_includes_dev_tools(tmp_path):
    (tmp_path / "requirements.in").write_text("pydantic>=2\n# ignored\ntrio\n")
    (tmp_path / "requirements-dev.in").write_text("-r requirements.in\npytest\n")

    assert _direct_requirements(tmp_path) == {"pydantic", "trio", "pytest"}


def test_validate_current_repository_passes():
    errors = validate(_repo_root())
    assert errors == []


def test_validate_missing_adr_fails(tmp_path):
    missing = tmp_path / "missing-adr"
    _copy_phase1_tree(missing)
    for adr in (missing / "docs/adr").glob("000*.md"):
        adr.unlink()
    errors = validate(missing)
    assert any("missing ADR" in error for error in errors)


def test_validate_proposed_adr_fails(tmp_path):
    proposed = tmp_path / "proposed-adr"
    _copy_phase1_tree(proposed)
    adr = next((proposed / "docs/adr").glob("0001-*.md"))
    adr.write_text(adr.read_text(encoding="utf-8").replace("accepted", "proposed"))
    errors = validate(proposed)
    assert any("ADR 0001 is not accepted" in error for error in errors)


def test_validate_missing_workflow_transition_fails(tmp_path):
    broken = tmp_path / "broken-workflow"
    _copy_phase1_tree(broken)
    workflow = broken / "docs/refactor/workflow-specification.md"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace("## Transition table", "## Removed")
    )
    errors = validate(broken)
    assert any("Transition table" in error for error in errors)


def test_validate_placeholder_characterization_fails(tmp_path):
    broken = tmp_path / "broken-characterization"
    _copy_phase1_tree(broken)
    onboarding = broken / "tests/characterization/test_onboarding_flow.py"
    onboarding.write_text("def test_placeholder():\n    raise NotImplementedError\n")
    errors = validate(broken)
    assert any("placeholder characterization" in error for error in errors)


def test_validate_incomplete_deletion_inventory_fails(tmp_path):
    broken = tmp_path / "broken-deletion"
    _copy_phase1_tree(broken)
    inventory = broken / "docs/refactor/deletion-inventory.md"
    inventory.write_text("| Path / symbols | Responsibility |\n|---|---|\n")
    errors = validate(broken)
    assert any("deletion inventory column" in error for error in errors)
