import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "validate_refactor_phase_6.py"
)
_SPEC = importlib.util.spec_from_file_location("validate_refactor_phase_6", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules["validate_refactor_phase_6"] = _MODULE
_SPEC.loader.exec_module(_MODULE)
validate = _MODULE.validate
parse_manifest = _MODULE.parse_manifest
_invoked_make_targets = _MODULE._invoked_make_targets
_invoked_scripts = _MODULE._invoked_scripts
_RecipeCommand = _MODULE.RecipeCommand
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_manifest(
    root: Path,
    *,
    status: str = "active",
    items: str,
) -> None:
    docs = root / "docs/refactor"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "deletion-manifest.toml").write_text(
        f'schema_version = 1\nstatus = "{status}"\n\n{items}',
        encoding="utf-8",
    )


_MINIMAL_DOCKERFILE = """\
FROM python:3.11-slim AS base
FROM base AS runtime
CMD ["python", "-m", "psychoanalyst_app.server"]
FROM base AS development
CMD ["python", "-m", "psychoanalyst_app.server"]
"""

_MINIMAL_DOCKERFILE_TARGET = """\
FROM python:3.11-slim AS base
FROM base AS runtime
CMD ["jung-api"]
FROM base AS development
CMD ["jung-api"]
"""

_MINIMAL_COMPOSE_LEGACY = """\
x-api-base: &api-base
  build:
    context: .
    dockerfile: Dockerfile
    target: development
  command: python -m psychoanalyst_app.server

services:
  api:
    <<: *api-base
"""

_MINIMAL_COMPOSE_TARGET = """\
x-api-base: &api-base
  build:
    context: .
    dockerfile: Dockerfile
    target: development
  command: jung-api

services:
  api:
    <<: *api-base
"""

_MINIMAL_PYPROJECT_LEGACY = """\
[project]
name = "psychoanalyst"
version = "0.0.0"
dependencies = ["fastapi"]

[project.scripts]
psychoanalyst-server = "psychoanalyst_app.server:cli"
"""

_MINIMAL_PYPROJECT_TARGET = """\
[project]
name = "jung"
version = "0.0.0"
dependencies = ["fastapi"]

[project.scripts]
jung-api = "jung.api.app:cli"
jung-console = "jung.client.terminal:cli"
jung-db = "jung.tools.db_backup:main"
"""

_LEGACY_GATE = """\
finalization-check: prepare-runtime-dirs
\t$(MAKE) lint
\t$(MAKE) validate-docs
\t$(MAKE) validate-schemas
\t$(MAKE) validate-generated-contracts
\t$(MAKE) validate-architecture
\t$(MAKE) test-validate
\tpython scripts/validate_refactor_phase_5.py
\t$(MAKE) characterization-smoke
\t$(MAKE) probe-console-deterministic
"""

_TARGET_GATE = """\
finalization-check-target: prepare-runtime-dirs
\t$(MAKE) lint
\t$(MAKE) validate-docs
\t$(MAKE) test-target
\tpython scripts/validate_refactor_phase_6.py
\tpython scripts/validate_refactor_phase_5.py
\t$(MAKE) probe-console-v1-deterministic
"""

_CUTOVER_GATE = """\
finalization-check: prepare-runtime-dirs
\t$(MAKE) lint
\t$(MAKE) validate-docs
\t$(MAKE) test-target
\tpython scripts/validate_refactor_phase_6.py
\tpython scripts/validate_refactor_phase_5.py
\t$(MAKE) probe-console-v1-deterministic
"""

_BASE_MAKEFILE = """\
.PHONY: prepare-runtime-dirs lint validate-docs test-target test-validate \\
\tvalidate-schemas validate-generated-contracts validate-architecture \\
\tcharacterization-smoke probe-console-deterministic \\
\tprobe-console-v1-deterministic finalization-check finalization-check-target
prepare-runtime-dirs:
\t@true
lint:
\t@true
validate-docs:
\t@true
test-target:
\tpytest tests/
test-validate:
\t@true
validate-schemas:
\t@true
validate-generated-contracts:
\t@true
validate-architecture:
\t@true
characterization-smoke:
\t@true
probe-console-deterministic:
\t@true
probe-console-v1-deterministic:
\t@true
"""


def _write_runtime(
    root: Path,
    *,
    target: bool = False,
    dockerfile: str | None = None,
    compose: str | None = None,
    makefile_extra: str | None = None,
) -> None:
    gates = makefile_extra
    if gates is None:
        gates = _CUTOVER_GATE if target else _LEGACY_GATE + _TARGET_GATE
    (root / "Makefile").write_text(
        _BASE_MAKEFILE + gates, encoding="utf-8"
    )
    (root / "Dockerfile").write_text(
        dockerfile or (_MINIMAL_DOCKERFILE_TARGET if target else _MINIMAL_DOCKERFILE),
        encoding="utf-8",
    )
    (root / "docker-compose.yml").write_text(
        compose or (_MINIMAL_COMPOSE_TARGET if target else _MINIMAL_COMPOSE_LEGACY),
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        _MINIMAL_PYPROJECT_TARGET if target else _MINIMAL_PYPROJECT_LEGACY,
        encoding="utf-8",
    )
    (root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts/validate_refactor_phase_5.py").write_text("# stub\n", encoding="utf-8")
    (root / "scripts/validate_refactor_phase_6.py").write_text("# stub\n", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)


_COEXISTING_WORKFLOW = """\
name: Release Candidate Validation
on:
  pull_request:
jobs:
  finalization-check:
    runs-on: ubuntu-latest
    steps:
      - run: make finalization-check
  target-finalization-check:
    runs-on: ubuntu-latest
    steps:
      - run: make finalization-check-target
"""

_CUTOVER_WORKFLOW = """\
name: Release Candidate Validation
on:
  pull_request:
jobs:
  finalization-check:
    runs-on: ubuntu-latest
    steps:
      - run: make finalization-check
"""


def _write_workflow(root: Path, text: str) -> None:
    workflow_dir = root / ".github/workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / "release-candidate-validation.yml").write_text(
        text, encoding="utf-8"
    )


def _pre_cutover_manifest() -> str:
    return """
[[items]]
path = "probe-console-v1-deterministic"
kind = "make_target"
action = "retain"
owner_pr = "6A"
status = "complete"
confidence = "confirmed"
responsibility = "Target probe"

[[items]]
path = ".github/workflows/release-candidate-validation.yml"
kind = "workflow_edit"
action = "edit"
owner_pr = "6C"
status = "in_progress"
confidence = "confirmed"
responsibility = "Workflow cutover"
"""


def _seed_pre_cutover(root: Path) -> None:
    _write_manifest(root, items=_pre_cutover_manifest())
    _write_runtime(
        root,
        target=False,
        makefile_extra=_LEGACY_GATE + _TARGET_GATE,
    )
    _write_workflow(root, _COEXISTING_WORKFLOW)


def _seed_cutover(root: Path, *, workflow_complete: bool = False) -> None:
    status = "complete" if workflow_complete else "in_progress"
    manifest = _pre_cutover_manifest().replace(
        'status = "in_progress"', f'status = "{status}"'
    )
    _write_manifest(root, items=manifest)
    _write_runtime(root, target=True, makefile_extra=_CUTOVER_GATE)
    _write_workflow(
        root, _CUTOVER_WORKFLOW if workflow_complete else _COEXISTING_WORKFLOW
    )


def _seed_final(root: Path) -> None:
    items = """
[[items]]
path = "gone/"
kind = "filesystem"
action = "delete"
aggregate = true
owner_pr = "6D"
status = "complete"
confidence = "confirmed"
responsibility = "Removed legacy root"

[[items]]
path = ".github/workflows/release-candidate-validation.yml"
kind = "workflow_edit"
action = "edit"
owner_pr = "6C"
status = "complete"
confidence = "confirmed"
responsibility = "Target-only release gate"
"""
    _write_manifest(root, status="completed", items=items)
    _write_runtime(root, target=True, makefile_extra=_CUTOVER_GATE)
    _write_workflow(root, _CUTOVER_WORKFLOW)
    (root / "src").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)


def test_valid_pre_cutover_passes(tmp_path):
    _seed_pre_cutover(tmp_path)
    assert validate(tmp_path, stage="pre-cutover") == []


def test_valid_cutover_passes_when_workflow_complete(tmp_path):
    _seed_cutover(tmp_path, workflow_complete=True)
    assert validate(tmp_path, stage="cutover") == []


def test_valid_final_passes(tmp_path):
    _seed_final(tmp_path)
    assert validate(tmp_path, stage="final") == []


@pytest.mark.parametrize(
    ("stage", "status"),
    [
        ("pre-cutover", "completed"),
        ("cutover", "completed"),
        ("final", "active"),
    ],
)
def test_manifest_status_rejected_for_stage(tmp_path, stage, status):
    _seed_pre_cutover(tmp_path)
    _write_manifest(tmp_path, status=status, items=_pre_cutover_manifest())
    errors = validate(tmp_path, stage=stage)
    assert any("manifest status" in error for error in errors)


def test_cutover_rejects_in_progress_workflow_edit(tmp_path):
    _seed_cutover(tmp_path, workflow_complete=False)
    errors = validate(tmp_path, stage="cutover")
    assert any("required item must be complete" in error for error in errors)


def test_cutover_rejects_workflow_with_phase1_job(tmp_path):
    _seed_cutover(tmp_path, workflow_complete=True)
    workflow = (tmp_path / ".github/workflows/release-candidate-validation.yml").read_text(
        encoding="utf-8"
    )
    workflow += """
  phase-1-evidence:
    steps:
      - run: make validate-refactor-phase-1
"""
    _write_workflow(tmp_path, workflow)
    errors = validate(tmp_path, stage="cutover")
    assert any("phase-1-evidence" in error for error in errors)


def test_completed_deletion_still_present_fails(tmp_path):
    _seed_pre_cutover(tmp_path)
    extra = """
[[items]]
path = "legacy.txt"
kind = "filesystem"
action = "delete"
owner_pr = "6C"
status = "complete"
confidence = "confirmed"
responsibility = "Gone"
"""
    _write_manifest(
        tmp_path,
        items=_pre_cutover_manifest() + extra,
    )
    (tmp_path / "legacy.txt").write_text("x", encoding="utf-8")
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("still present" in error for error in errors)


def test_missing_concrete_replacement_fails(tmp_path):
    _seed_pre_cutover(tmp_path)
    extra = """
[[items]]
path = "legacy.py"
kind = "filesystem"
action = "port_then_delete"
owner_pr = "6D"
status = "complete"
confidence = "confirmed"
responsibility = "Ported"
replacements = ["missing/replacement.py"]
"""
    _write_manifest(tmp_path, items=_pre_cutover_manifest() + extra)
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("missing path" in error for error in errors)


def test_retained_make_target_absent_fails(tmp_path):
    _seed_pre_cutover(tmp_path)
    extra = """
[[items]]
path = "missing-target"
kind = "make_target"
action = "retain"
owner_pr = "6A"
status = "complete"
confidence = "confirmed"
responsibility = "Missing target"
"""
    _write_manifest(tmp_path, items=_pre_cutover_manifest() + extra)
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("retained path missing" in error for error in errors)


def test_forbidden_dependency_in_pyproject_fails(tmp_path):
    _seed_final(tmp_path)
    pyproject = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    pyproject = pyproject.replace(
        'dependencies = ["fastapi"]',
        'dependencies = ["fastapi", "trio"]',
    )
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    errors = validate(tmp_path, stage="final")
    assert any("forbidden dependency" in error for error in errors)


def test_forbidden_dependency_in_requirements_fails(tmp_path):
    _seed_final(tmp_path)
    (tmp_path / "requirements.txt").write_text("quart\n", encoding="utf-8")
    errors = validate(tmp_path, stage="final")
    assert any("forbidden dependency" in error for error in errors)


def test_forbidden_import_fails(tmp_path):
    _seed_final(tmp_path)
    legacy = tmp_path / "src/legacy.py"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("import psychoanalyst_app\n", encoding="utf-8")
    errors = validate(tmp_path, stage="final")
    assert any("imports forbidden module" in error for error in errors)


def test_non_final_selected_docker_stage_passes(tmp_path):
    _seed_pre_cutover(tmp_path)
    dockerfile = """\
FROM python:3.11-slim AS base
FROM base AS development
CMD ["python", "-m", "psychoanalyst_app.server"]
FROM base AS runtime
CMD ["jung-api"]
"""
    compose = """\
x-api-base: &api-base
  build:
    context: .
    dockerfile: Dockerfile
    target: development
  command: python -m psychoanalyst_app.server
services:
  api:
    <<: *api-base
"""
    _write_runtime(tmp_path, target=False, dockerfile=dockerfile, compose=compose)
    assert validate(tmp_path, stage="pre-cutover") == []


def test_non_final_selected_stage_fails_when_only_final_correct(tmp_path):
    _seed_pre_cutover(tmp_path)
    dockerfile = """\
FROM python:3.11-slim AS base
FROM base AS development
CMD ["jung-api"]
FROM base AS runtime
CMD ["python", "-m", "psychoanalyst_app.server"]
"""
    compose = """\
x-api-base: &api-base
  build:
    context: .
    dockerfile: Dockerfile
    target: development
  command: python -m psychoanalyst_app.server
services:
  api:
    <<: *api-base
"""
    _write_runtime(tmp_path, target=False, dockerfile=dockerfile, compose=compose)
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("CMD must select" in error for error in errors)


def test_unknown_explicit_build_target_fails(tmp_path):
    _seed_pre_cutover(tmp_path)
    compose = """\
x-api-base: &api-base
  build:
    context: .
    dockerfile: Dockerfile
    target: missing-stage
  command: python -m psychoanalyst_app.server
services:
  api:
    <<: *api-base
"""
    _write_runtime(tmp_path, target=False, compose=compose)
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("does not match any Dockerfile stage" in error for error in errors)


def test_compose_command_override_mismatch_fails(tmp_path):
    _seed_pre_cutover(tmp_path)
    compose = _MINIMAL_COMPOSE_LEGACY.replace(
        "command: python -m psychoanalyst_app.server",
        "command: jung-api",
    )
    _write_runtime(tmp_path, target=False, compose=compose)
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("docker-compose api command must select" in error for error in errors)


def test_missing_target_gate_step_fails(tmp_path):
    _seed_pre_cutover(tmp_path)
    makefile = (tmp_path / "Makefile").read_text(encoding="utf-8")
    makefile = makefile.replace("$(MAKE) test-target\n", "")
    (tmp_path / "Makefile").write_text(makefile, encoding="utf-8")
    errors = validate(tmp_path, stage="pre-cutover")
    assert any(
        "finalization-check-target must invoke test-target" in error
        for error in errors
    )


@pytest.mark.parametrize(
    ("recipe", "target", "expected"),
    [
        ("@echo probe-console-deterministic", "probe-console-deterministic", False),
        ("@echo test-target", "test-target", False),
        ("-$(MAKE) test-target", "test-target", False),
        ("$(MAKE) probe-console-v1-deterministic", "probe-console-deterministic", False),
        ("$(MAKE) probe-console-deterministic", "probe-console-deterministic", True),
    ],
)
def test_gate_make_target_false_positives(recipe, target, expected):
    commands = [_RecipeCommand(text=recipe, ignored_failure=recipe.startswith("-"))]
    assert (target in _invoked_make_targets(commands)) is expected


@pytest.mark.parametrize(
    ("recipe", "script", "expected"),
    [
        ("python scripts/validate_refactor_phase_6.py", "scripts/validate_refactor_phase_6.py", True),
        ("python scripts/validate_refactor_phase_6.py.old", "scripts/validate_refactor_phase_6.py", False),
        ("echo scripts/validate_refactor_phase_6.py", "scripts/validate_refactor_phase_6.py", False),
    ],
)
def test_gate_script_exact_match(recipe, script, expected):
    commands = [_RecipeCommand(text=recipe, ignored_failure=False)]
    assert (script in _invoked_scripts(commands)) is expected


def test_unknown_top_level_manifest_field_fails(tmp_path):
    docs = tmp_path / "docs/refactor"
    docs.mkdir(parents=True)
    (docs / "deletion-manifest.toml").write_text(
        'schema_version = 1\nstatus = "active"\nextra = true\n\n'
        + _pre_cutover_manifest(),
        encoding="utf-8",
    )
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None
    assert any("unknown top-level" in error for error in errors)


def test_absolute_manifest_path_fails(tmp_path):
    item = """
[[items]]
path = "/etc/passwd"
kind = "filesystem"
action = "delete"
owner_pr = "6C"
status = "planned"
confidence = "confirmed"
responsibility = "Bad path"
"""
    _write_manifest(tmp_path, items=item)
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None
    assert any("repository-relative" in error for error in errors)


def test_planned_discovery_needed_port_without_replacement_passes(tmp_path):
    item = """
[[items]]
path = "tests/unit/test_planning_analysis.py"
kind = "filesystem"
action = "port_then_delete"
owner_pr = "6D"
status = "planned"
confidence = "discovery-needed"
responsibility = "Unresolved planning coverage"
"""
    _write_manifest(tmp_path, items=item)
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is not None
    assert errors == []


@pytest.mark.parametrize(
    ("status", "confidence"),
    [
        ("planned", "confirmed"),
        ("complete", "confirmed"),
        ("in_progress", "confirmed"),
    ],
)
def test_port_without_replacement_fails_unless_discovery_needed(
    tmp_path, status, confidence
):
    item = f"""
[[items]]
path = "tests/unit/test_planning_analysis.py"
kind = "filesystem"
action = "port_then_delete"
owner_pr = "6D"
status = "{status}"
confidence = "{confidence}"
responsibility = "Needs replacement"
"""
    _write_manifest(tmp_path, items=item)
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None
    assert any("requires replacements" in error for error in errors)


def test_live_manifest_parses(tmp_path):
    manifest_src = _REPO_ROOT / "docs/refactor/deletion-manifest.toml"
    docs = tmp_path / "docs/refactor"
    docs.mkdir(parents=True)
    (docs / "deletion-manifest.toml").write_text(
        manifest_src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is not None
    assert errors == []
