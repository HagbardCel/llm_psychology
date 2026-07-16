"""Unit tests for Phase 6 refactor validation."""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "validate_refactor_phase_6.py"
)
_SPEC = importlib.util.spec_from_file_location("validate_refactor_phase_6", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

TARGET_GATE_INVOCATIONS = _MODULE.TARGET_GATE_INVOCATIONS
LEGACY_GATE_INVOCATIONS = _MODULE.LEGACY_GATE_INVOCATIONS
validate = _MODULE.validate
_recipe_text = _MODULE._recipe_text


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _inventory_text() -> str:
    return textwrap.dedent(
        """
        ---
        owner: engineering
        status: active
        source_of_truth_for: Planned legacy deletion inventory
        ---

        # Deletion Inventory

        ## Filesystem deletion roots

        - `src/psychoanalyst_app/`
        - `console-ui/`

        ## Legacy Make targets

        - `characterization-smoke`

        ## Legacy CI workflows

        - `.github/workflows/architecture-governance.yml`

        ## Exceptions

        | Path | Treatment | Owner PR | Status | Evidence |
        |---|---|---|---|---|
        | `src/psychoanalyst_app/tools/db_backup.py` | reimplement_minimal | 6B | planned | jung.tools backup |
        | `tests/unit/test_measure_codebase.py` | retain_test | 6A | complete | test-target support |
        """
    ).lstrip()


def _write_pre_cutover_tree(root: Path) -> None:
    (root / "docs/refactor").mkdir(parents=True)
    (root / "docs/refactor/deletion-inventory.md").write_text(
        _inventory_text(), encoding="utf-8"
    )
    (root / "src/psychoanalyst_app/tools").mkdir(parents=True)
    (root / "src/psychoanalyst_app/tools/db_backup.py").write_text(
        "# legacy backup\n", encoding="utf-8"
    )
    for relative in _MODULE.TARGET_SUPPORT_TESTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    (root / "docker-compose.yml").write_text(
        textwrap.dedent(
            """
            services:
              api:
                command: python -m psychoanalyst_app.server
                healthcheck:
                  test: ["CMD", "wget", "http://localhost:8000/health"]
            """
        ).lstrip(),
        encoding="utf-8",
    )
    (root / "Dockerfile").write_text(
        'CMD ["python", "-m", "psychoanalyst_app.server"]\n',
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project.scripts]
            jung-api = "jung.api.app:cli"
            jung-console = "jung.client.terminal:cli"
            psychoanalyst-server = "psychoanalyst_app.server:cli"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "Makefile").write_text(
        textwrap.dedent(
            """
            test-target:
            \tdocker compose test-target-body

            smoke-target-local-llm: smoke-refactor-phase-3-local-llm

            validate-refactor-phase-6:
            \tpython scripts/validate_refactor_phase_6.py --stage pre-cutover

            probe-console-v1-deterministic:
            \tprobe body

            finalization-check-target: prepare-runtime-dirs
            \t$(MAKE) lint
            \t$(MAKE) validate-docs
            \t$(MAKE) test-target
            \tdocker compose run test python scripts/validate_refactor_phase_6.py --stage pre-cutover
            \tdocker compose run test python scripts/validate_refactor_phase_5.py
            \t$(MAKE) probe-console-v1-deterministic

            finalization-check: prepare-runtime-dirs
            \t$(MAKE) validate-schemas
            \t$(MAKE) validate-generated-contracts
            \t$(MAKE) validate-architecture
            \t$(MAKE) test-validate
            \tpython scripts/validate_refactor_phase_5.py
            \t$(MAKE) characterization-smoke
            \t$(MAKE) probe-console-deterministic
            """
        ).lstrip(),
        encoding="utf-8",
    )


def test_validate_current_repository_pre_cutover_passes() -> None:
    errors = validate(_repo_root(), stage="pre-cutover")
    assert errors == []


def test_pre_cutover_requires_candidate_gate_without_legacy_steps(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    candidate = _recipe_text(tmp_path, "finalization-check-target")
    assert _MODULE._gate_uses_invocations(candidate, TARGET_GATE_INVOCATIONS) == []
    assert _MODULE._gate_forbids_invocations(candidate, LEGACY_GATE_INVOCATIONS) == []


def test_pre_cutover_requires_legacy_canonical_gate(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    makefile = tmp_path / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    makefile.write_text(
        text.replace("\t$(MAKE) validate-schemas\n", ""),
        encoding="utf-8",
    )
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("gate missing required step" in item for item in errors)


def test_cutover_requires_jung_runtime_and_target_gate(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    (tmp_path / "docker-compose.yml").write_text(
        textwrap.dedent(
            """
            services:
              api:
                command: ["jung-api"]
                healthcheck:
                  test: ["CMD", "wget", "http://localhost:8000/api/v1/health"]
            """
        ).lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "Dockerfile").write_text('CMD ["jung-api"]\n', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project.scripts]
            jung-api = "jung.api.app:cli"
            jung-console = "jung.client.terminal:cli"
            jung-db = "jung.tools.db_backup:main"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "Makefile").write_text(
        textwrap.dedent(
            """
            test-target:
            probe-console-v1-deterministic:
            finalization-check: prepare-runtime-dirs
            \t$(MAKE) test-target
            \tpython scripts/validate_refactor_phase_6.py --stage cutover
            \tpython scripts/validate_refactor_phase_5.py
            \t$(MAKE) probe-console-v1-deterministic
            """
        ).lstrip(),
        encoding="utf-8",
    )
    errors = validate(tmp_path, stage="cutover")
    assert errors == []


def test_gate_lifecycle_table_matches_repository_stage() -> None:
    root = _repo_root()
    candidate = _recipe_text(root, "finalization-check-target")
    canonical = _recipe_text(root, "finalization-check")

    assert "--stage pre-cutover" in candidate
    assert "validate-schemas" not in candidate
    assert "probe-console-deterministic" not in candidate

    assert "$(MAKE) validate-schemas" in canonical
    assert "$(MAKE) probe-console-deterministic" in canonical
    assert "--stage cutover" not in canonical
    assert "--final" not in canonical


def test_inventory_rejects_duplicate_exception_paths(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    text = (tmp_path / "docs/refactor/deletion-inventory.md").read_text(
        encoding="utf-8"
    )
    duplicate_row = (
        "| `src/psychoanalyst_app/tools/db_backup.py` | reimplement_minimal "
        "| 6B | planned | duplicate |"
    )
    (tmp_path / "docs/refactor/deletion-inventory.md").write_text(
        text + "\n" + duplicate_row + "\n",
        encoding="utf-8",
    )
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("duplicate inventory exception path" in item for item in errors)
