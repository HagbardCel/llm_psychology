import importlib.util
import shutil
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
_RecipeCommand = _MODULE.RecipeCommand


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_manifest(
    root: Path,
    *,
    status: str = "active",
    items: str | None = None,
) -> None:
    docs = root / "docs/refactor"
    docs.mkdir(parents=True, exist_ok=True)
    if items is None:
        shutil.copy2(_repo_root() / "docs/refactor/deletion-manifest.toml", docs)
        text = (docs / "deletion-manifest.toml").read_text(encoding="utf-8")
        text = text.replace('status = "active"', f'status = "{status}"', 1)
        (docs / "deletion-manifest.toml").write_text(text, encoding="utf-8")
        return
    (docs / "deletion-manifest.toml").write_text(
        f'schema_version = 1\nstatus = "{status}"\n\n{items}',
        encoding="utf-8",
    )


_RETAINED_TEST_PATHS = (
    "tests/unit/test_measure_codebase.py",
    "tests/unit/test_validate_refactor_phase_5.py",
    "tests/unit/test_recording_fake_llm.py",
    "tests/unit/test_validate_refactor_phase_6.py",
    "tests/e2e/test_console_v1_workflow.py",
)


def _copy_retained_tests(root: Path) -> None:
    repo = _repo_root()
    for relative in _RETAINED_TEST_PATHS:
        source = repo / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            shutil.copy2(source, target)


def _write_runtime_files(root: Path, *, target: bool = False) -> None:
    shutil.copy2(_repo_root() / "Makefile", root / "Makefile")
    shutil.copy2(_repo_root() / "docker-compose.yml", root / "docker-compose.yml")
    shutil.copy2(_repo_root() / "Dockerfile", root / "Dockerfile")
    shutil.copy2(_repo_root() / "pyproject.toml", root / "pyproject.toml")
    shutil.copy2(_repo_root() / "requirements.txt", root / "requirements.txt")
    if target:
        compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
        compose = compose.replace(
            "command: python -m psychoanalyst_app.server",
            "command: jung-api",
        )
        (root / "docker-compose.yml").write_text(compose, encoding="utf-8")
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        dockerfile = dockerfile.replace(
            'CMD ["python", "-m", "psychoanalyst_app.server"]',
            'CMD ["jung-api"]',
        )
        (root / "Dockerfile").write_text(dockerfile, encoding="utf-8")
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        pyproject = pyproject.replace(
            'psychoanalyst-server = "psychoanalyst_app.server:cli"\n'
            'psychoanalyst-db = "psychoanalyst_app.tools.db_backup:main"\n',
            "",
        )
        (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")


def _seed_pre_cutover_tree(root: Path) -> None:
    _write_manifest(root)
    _write_runtime_files(root, target=False)
    _copy_retained_tests(root)


def _target_gate_makefile(text: str) -> str:
    legacy = """finalization-check: prepare-runtime-dirs
\t$(MAKE) lint
\t$(MAKE) validate-docs
\t$(MAKE) validate-schemas
\t$(MAKE) validate-generated-contracts
\t$(MAKE) validate-architecture
\t$(MAKE) test-validate
\tdocker compose --profile test run --rm \\
\t\ttest python scripts/validate_refactor_phase_5.py
\t$(MAKE) characterization-smoke
\t$(MAKE) probe-console-deterministic"""
    target = """finalization-check: prepare-runtime-dirs
\t$(MAKE) lint
\t$(MAKE) validate-docs
\t$(MAKE) test-target
\tdocker compose --profile test run --rm \\
\t\ttest python scripts/validate_refactor_phase_6.py --stage cutover
\tdocker compose --profile test run --rm \\
\t\ttest python scripts/validate_refactor_phase_5.py
\t$(MAKE) probe-console-v1-deterministic"""
    return text.replace(legacy, target)


_COEXISTING_WORKFLOW = """name: Release Candidate Validation
on:
  pull_request:
jobs:
  finalization-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make finalization-check
  target-finalization-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make finalization-check-target
"""


def _write_coexisting_workflow(root: Path) -> None:
    workflow_dir = root / ".github/workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / "release-candidate-validation.yml").write_text(
        _COEXISTING_WORKFLOW, encoding="utf-8"
    )


def _seed_cutover_tree(root: Path) -> None:
    _write_manifest(root)
    _write_runtime_files(root, target=True)
    _copy_retained_tests(root)
    makefile = _target_gate_makefile((root / "Makefile").read_text(encoding="utf-8"))
    (root / "Makefile").write_text(makefile, encoding="utf-8")
    _write_coexisting_workflow(root)


def _seed_final_tree(root: Path) -> None:
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
    _write_runtime_files(root, target=True)
    makefile = _target_gate_makefile((root / "Makefile").read_text(encoding="utf-8"))
    (root / "Makefile").write_text(makefile, encoding="utf-8")
    workflow = """name: Release Candidate Validation
on:
  pull_request:
jobs:
  finalization-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make finalization-check
"""
    workflow_dir = root / ".github/workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / "release-candidate-validation.yml").write_text(
        workflow, encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        """[project]
name = "jung"
version = "0.0.0"
dependencies = ["fastapi", "pydantic"]

[project.scripts]
jung-api = "jung.api.app:cli"
jung-console = "jung.client.terminal:cli"
jung-db = "jung.tools.db_backup:main"

[tool.setuptools]
package-dir = { "" = "src" }
""",
        encoding="utf-8",
    )
    (root / "requirements.txt").write_text("fastapi\nuvicorn\npydantic\n", encoding="utf-8")
    (root / "src").mkdir(exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)


def test_valid_pre_cutover_passes(tmp_path):
    _seed_pre_cutover_tree(tmp_path)
    assert validate(tmp_path, stage="pre-cutover") == []


def test_valid_cutover_passes(tmp_path):
    _seed_cutover_tree(tmp_path)
    assert validate(tmp_path, stage="cutover") == []


def test_valid_final_passes(tmp_path):
    _seed_final_tree(tmp_path)
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
    _seed_pre_cutover_tree(tmp_path)
    _write_manifest(tmp_path, status=status)
    errors = validate(tmp_path, stage=stage)
    assert any("manifest status" in error for error in errors)


def test_completed_manifest_with_incomplete_item_fails(tmp_path):
    _seed_final_tree(tmp_path)
    text = (tmp_path / "docs/refactor/deletion-manifest.toml").read_text(
        encoding="utf-8"
    )
    text = text.replace("status = \"complete\"", "status = \"planned\"", 1)
    (tmp_path / "docs/refactor/deletion-manifest.toml").write_text(text, encoding="utf-8")
    errors = validate(tmp_path, stage="final")
    assert any("not complete" in error for error in errors)


def test_completed_item_still_present_fails(tmp_path):
    _seed_pre_cutover_tree(tmp_path)
    text = (tmp_path / "docs/refactor/deletion-manifest.toml").read_text(
        encoding="utf-8"
    )
    extra = """
[[items]]
path = "src/psychoanalyst_app/server.py"
kind = "filesystem"
action = "delete"
owner_pr = "6C"
status = "complete"
confidence = "confirmed"
responsibility = "Should be gone"
"""
    (tmp_path / "docs/refactor/deletion-manifest.toml").write_text(
        text + extra, encoding="utf-8"
    )
    (tmp_path / "src/psychoanalyst_app").mkdir(parents=True)
    (tmp_path / "src/psychoanalyst_app/server.py").write_text("# legacy\n")
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("still present" in error for error in errors)


@pytest.mark.parametrize(
    ("kind", "path", "write"),
    [
        ("filesystem", "legacy.txt", lambda root: (root / "legacy.txt").write_text("x")),
        ("make_target", "legacy-target", lambda root: (root / "Makefile").write_text(
            (root / "Makefile").read_text(encoding="utf-8")
            + "\nlegacy-target:\n\t@true\n"
        )),
        (
            "workflow",
            ".github/workflows/legacy.yml",
            lambda root: (
                root / ".github/workflows/legacy.yml"
            ).write_text("name: legacy\n"),
        ),
    ],
)
def test_final_residual_item_fails(tmp_path, kind, path, write):
    _seed_final_tree(tmp_path)
    text = (tmp_path / "docs/refactor/deletion-manifest.toml").read_text(
        encoding="utf-8"
    )
    extra = f"""
[[items]]
path = "{path}"
kind = "{kind}"
action = "delete"
owner_pr = "6C"
status = "complete"
confidence = "confirmed"
responsibility = "Residual"
"""
    (tmp_path / "docs/refactor/deletion-manifest.toml").write_text(
        text + extra, encoding="utf-8"
    )
    if kind == "workflow":
        (tmp_path / ".github/workflows").mkdir(parents=True, exist_ok=True)
    write(tmp_path)
    errors = validate(tmp_path, stage="final")
    assert any("still present" in error for error in errors)


def test_completed_item_missing_replacement_fails(tmp_path):
    _seed_pre_cutover_tree(tmp_path)
    extra = """
[[items]]
path = "src/legacy_only.py"
kind = "filesystem"
action = "port_then_delete"
owner_pr = "6D"
status = "complete"
confidence = "confirmed"
responsibility = "Ported module"
replacements = ["src/missing_replacement.py"]
evidence = ["tests/unit/jung/test_composition.py"]
"""
    text = (tmp_path / "docs/refactor/deletion-manifest.toml").read_text(
        encoding="utf-8"
    )
    (tmp_path / "docs/refactor/deletion-manifest.toml").write_text(
        text + extra, encoding="utf-8"
    )
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("missing path" in error for error in errors)


def test_unapplied_workflow_edit_fails(tmp_path):
    _seed_cutover_tree(tmp_path)
    workflow = (tmp_path / ".github/workflows/release-candidate-validation.yml").read_text(
        encoding="utf-8"
    )
    workflow += """
  phase-1-evidence:
    needs: finalization-check
    steps:
      - run: make validate-refactor-phase-1
"""
    (tmp_path / ".github/workflows/release-candidate-validation.yml").write_text(
        workflow, encoding="utf-8"
    )
    text = (tmp_path / "docs/refactor/deletion-manifest.toml").read_text(
        encoding="utf-8"
    )
    text = text.replace(
        'status = "in_progress"',
        'status = "complete"',
    )
    (tmp_path / "docs/refactor/deletion-manifest.toml").write_text(text, encoding="utf-8")
    errors = validate(tmp_path, stage="cutover")
    assert any("phase-1-evidence" in error for error in errors)


def test_wrong_runtime_comment_only_fails(tmp_path):
    _seed_pre_cutover_tree(tmp_path)
    dockerfile = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
    dockerfile = dockerfile.replace(
        'CMD ["python", "-m", "psychoanalyst_app.server"]',
        'CMD ["jung-api"]',
    )
    (tmp_path / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("must select" in error for error in errors)


def test_missing_target_gate_invocation_fails(tmp_path):
    _seed_pre_cutover_tree(tmp_path)
    makefile = (tmp_path / "Makefile").read_text(encoding="utf-8")
    makefile = makefile.replace("$(MAKE) test-target\n", "")
    (tmp_path / "Makefile").write_text(makefile, encoding="utf-8")
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("finalization-check-target must invoke test-target" in error for error in errors)


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
def test_gate_invocation_false_positives(recipe, target, expected):
    commands = [_RecipeCommand(text=recipe, ignored_failure=recipe.startswith("-"))]
    assert (target in _invoked_make_targets(commands)) is expected


def test_unknown_manifest_field_fails(tmp_path):
    _seed_pre_cutover_tree(tmp_path)
    text = (tmp_path / "docs/refactor/deletion-manifest.toml").read_text(
        encoding="utf-8"
    )
    text = text.replace(
        "responsibility = ",
        "replacement = [\"oops\"]\nresponsibility = ",
        1,
    )
    (tmp_path / "docs/refactor/deletion-manifest.toml").write_text(text, encoding="utf-8")
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None
    assert any("unknown field" in error for error in errors)


def test_complete_non_confirmed_confidence_fails(tmp_path):
    _seed_pre_cutover_tree(tmp_path)
    text = (tmp_path / "docs/refactor/deletion-manifest.toml").read_text(
        encoding="utf-8"
    )
    text = text.replace(
        'confidence = "confirmed"\nresponsibility = "Codebase measurement',
        'confidence = "likely"\nresponsibility = "Codebase measurement',
        1,
    )
    (tmp_path / "docs/refactor/deletion-manifest.toml").write_text(text, encoding="utf-8")
    manifest, errors = parse_manifest(tmp_path)
    assert manifest is None
    assert any("complete items must have confidence = confirmed" in error for error in errors)
