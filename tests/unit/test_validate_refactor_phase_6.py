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

validate = _MODULE.validate
_all_recipes = _MODULE._all_recipes
_require_recipe_text = _MODULE._require_recipe_text
_gate_forbids_make_target = _MODULE._gate_forbids_make_target
_logical_recipe_commands = _MODULE._logical_recipe_commands
_validator_gate_invocations = _MODULE._validator_gate_invocations
_matches_test_target = _MODULE._matches_test_target
RecipeCommand = _MODULE.RecipeCommand
TARGET_SUPPORT_TESTS = _MODULE.EXPECTED_TARGET_SUPPORT_TESTS


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _inventory_text(*, status: str = "active") -> str:
    return textwrap.dedent(
        f"""
        ---
        owner: engineering
        status: {status}
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

        ## Legacy CI workflow edits

        - `.github/workflows/release-candidate-validation.yml`

        ## Exceptions

        | Path | Treatment | Owner PR | Status | Evidence |
        |---|---|---|---|---|
        | `src/psychoanalyst_app/tools/db_backup.py` | reimplement_minimal | 6B | planned | jung.tools backup |
        | `tests/unit/test_measure_codebase.py` | retain_test | 6A | complete | test-target support |
        """
    ).lstrip()


def _canonical_pre_cutover_gate() -> str:
    return textwrap.dedent(
        """
        finalization-check: prepare-runtime-dirs
        \t$(MAKE) lint
        \t$(MAKE) validate-docs
        \t$(MAKE) validate-schemas
        \t$(MAKE) validate-generated-contracts
        \t$(MAKE) validate-architecture
        \t$(MAKE) test-validate
        \tdocker compose --profile test run --rm \\
        \t\ttest python scripts/validate_refactor_phase_5.py
        \t$(MAKE) characterization-smoke
        \t$(MAKE) probe-console-deterministic
        """
    ).lstrip()


def _candidate_pre_cutover_gate() -> str:
    return textwrap.dedent(
        """
        finalization-check-target: prepare-runtime-dirs
        \t$(MAKE) lint
        \t$(MAKE) validate-docs
        \t$(MAKE) test-target
        \tdocker compose --profile test run --rm \\
        \t\ttest python scripts/validate_refactor_phase_6.py --stage pre-cutover
        \tdocker compose --profile test run --rm \\
        \t\ttest python scripts/validate_refactor_phase_5.py
        \t$(MAKE) probe-console-v1-deterministic
        """
    ).lstrip()


def _test_target_recipe() -> str:
    return textwrap.dedent(
        """
        test-target: prepare-runtime-dirs
        \tdocker compose --profile test run --rm test pytest \\
        \t\t$(PHASE_6_PYTEST_OPTIONS) \\
        \t\t-m "not real_llm" \\
        \t\ttests/unit/jung/ \\
        \t\ttests/integration/jung/ \\
        \t\t$(TARGET_SUPPORT_TESTS)
        """
    ).lstrip()


def _makefile_preamble() -> str:
    return textwrap.dedent(
        """
        .PHONY: finalization-check finalization-check-target test-target \\
        \tprobe-console-v1-deterministic validate-refactor-phase-6

        TARGET_SUPPORT_TESTS := \\
        \ttests/unit/test_validate_refactor_phase_5.py \\
        \ttests/unit/test_validate_refactor_phase_6.py \\
        \ttests/unit/test_recording_fake_llm.py \\
        \ttests/unit/test_measure_codebase.py

        PHASE_6_PYTEST_OPTIONS := \\
        \t-o trio_mode=false \\
        \t-o asyncio_mode=auto

        smoke-target-local-llm: smoke-refactor-phase-3-local-llm
        smoke-refactor-phase-3-local-llm:
        \t@echo smoke

        prepare-runtime-dirs:
        \t@mkdir -p data logs
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
    for relative in TARGET_SUPPORT_TESTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    (root / "pytest.ini").write_text(
        textwrap.dedent(
            """
            [pytest]
            addopts =
                -v
                --tb=short
                --strict-markers
                --strict-config
            """
        ).lstrip(),
        encoding="utf-8",
    )
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
        _makefile_preamble()
        + _test_target_recipe()
        + "\n"
        + _candidate_pre_cutover_gate()
        + "\n"
        + _canonical_pre_cutover_gate(),
        encoding="utf-8",
    )


def test_validate_current_repository_pre_cutover_passes() -> None:
    errors = validate(_repo_root(), stage="pre-cutover")
    assert errors == []


def test_pre_cutover_candidate_gate_contract(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    make_recipes = _all_recipes(tmp_path)
    recipe, recipe_errors = _require_recipe_text(
        make_recipes, "finalization-check-target"
    )
    assert recipe_errors == []
    assert recipe is not None
    assert _gate_forbids_make_target(recipe, target="characterization-smoke") == []
    assert _gate_forbids_make_target(recipe, target="validate-schemas") == []


def test_pre_cutover_canonical_requires_legacy_steps(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    makefile = tmp_path / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    makefile.write_text(
        text.replace("\t$(MAKE) validate-schemas\n", ""),
        encoding="utf-8",
    )
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("gate must invoke $(MAKE) validate-schemas" in item for item in errors)


def test_pre_cutover_canonical_allows_shared_phase_5_validator(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    errors = validate(tmp_path, stage="pre-cutover")
    assert errors == []


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


def test_inventory_rejects_workflow_edit_bullet_prose(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    text = (tmp_path / "docs/refactor/deletion-inventory.md").read_text(
        encoding="utf-8"
    )
    bad = text.replace(
        "- `.github/workflows/release-candidate-validation.yml`",
        "- `.github/workflows/release-candidate-validation.yml` — remove phase-1-evidence",
    )
    (tmp_path / "docs/refactor/deletion-inventory.md").write_text(bad, encoding="utf-8")
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("malformed inventory bullet" in item for item in errors)


def test_inventory_rejects_invalid_make_target_identifier(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    text = (tmp_path / "docs/refactor/deletion-inventory.md").read_text(
        encoding="utf-8"
    )
    text = text.replace(
        "- `characterization-smoke`",
        "- `target with spaces`",
    )
    (tmp_path / "docs/refactor/deletion-inventory.md").write_text(text, encoding="utf-8")
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("invalid inventory make target" in item for item in errors)


def test_duplicate_finalization_check_definitions_fail(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        makefile.read_text(encoding="utf-8")
        + "\nfinalization-check:\n\t@true\n",
        encoding="utf-8",
    )
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("duplicate Makefile target definition: finalization-check" in item for item in errors)


def test_test_target_collect_only_in_options_fails(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    makefile = tmp_path / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    makefile.write_text(
        text.replace(
            "-o asyncio_mode=auto",
            "-o asyncio_mode=auto --collect-only",
        ),
        encoding="utf-8",
    )
    errors = validate(tmp_path, stage="pre-cutover")
    assert any(
        "forbidden pytest selection option" in item
        or "PHASE_6_PYTEST_OPTIONS must match" in item
        for item in errors
    )


def test_test_target_true_body_fails(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    makefile = tmp_path / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    makefile.write_text(
        text.replace(_test_target_recipe(), "test-target:\n\t@true\n"),
        encoding="utf-8",
    )
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("test-target must use the frozen deterministic pytest command" in item for item in errors)


def test_forbidden_legacy_only_in_comment_does_not_fail(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    makefile = tmp_path / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    makefile.write_text(
        text.replace(
            _candidate_pre_cutover_gate(),
            _candidate_pre_cutover_gate()
            + "\t# $(MAKE) characterization-smoke\n",
        ),
        encoding="utf-8",
    )
    errors = validate(tmp_path, stage="pre-cutover")
    assert not any("characterization-smoke" in item for item in errors)


def test_ignored_legacy_invocation_in_gate_fails(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    makefile = tmp_path / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    makefile.write_text(
        text.replace(
            _candidate_pre_cutover_gate(),
            _candidate_pre_cutover_gate() + "\t-$(MAKE) characterization-smoke\n",
        ),
        encoding="utf-8",
    )
    errors = validate(tmp_path, stage="pre-cutover")
    assert any("gate must not invoke legacy target: characterization-smoke" in item for item in errors)


def test_phase6_extra_validator_invocation_fails(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    makefile = tmp_path / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    makefile.write_text(
        text.replace(
            _candidate_pre_cutover_gate(),
            _candidate_pre_cutover_gate()
            + "\tpython scripts/validate_refactor_phase_6.py --unexpected\n",
        ),
        encoding="utf-8",
    )
    errors = validate(tmp_path, stage="pre-cutover")
    assert any(
        "gate must invoke scripts/validate_refactor_phase_6.py exactly once" in item
        for item in errors
    )


def test_phase6_env_prefixed_wrong_invocation_fails(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    makefile = tmp_path / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    makefile.write_text(
        text.replace(
            _candidate_pre_cutover_gate(),
            _candidate_pre_cutover_gate()
            + "\tFOO=bar docker compose --profile test run --rm test "
            "python scripts/validate_refactor_phase_6.py --unexpected\n",
        ),
        encoding="utf-8",
    )
    errors = validate(tmp_path, stage="pre-cutover")
    assert any(
        "gate must invoke scripts/validate_refactor_phase_6.py exactly once" in item
        for item in errors
    )


def test_matches_test_target_accepts_frozen_command() -> None:
    command = RecipeCommand(
        text=(
            'docker compose --profile test run --rm test pytest '
            '$(PHASE_6_PYTEST_OPTIONS) -m "not real_llm" tests/unit/jung/ '
            "tests/integration/jung/ $(TARGET_SUPPORT_TESTS)"
        ),
        ignore_errors=False,
    )
    assert _matches_test_target(command)


def test_validator_gate_invocations_counts_direct_python() -> None:
    recipe = textwrap.dedent(
        """
        target:
        \tdocker compose --profile test run --rm test python scripts/validate_refactor_phase_6.py --final
        \tpython scripts/validate_refactor_phase_6.py --unexpected
        """
    ).lstrip()
    invocations = _validator_gate_invocations(
        recipe, script="scripts/validate_refactor_phase_6.py"
    )
    assert len(invocations) == 2


def test_gate_lifecycle_table_matches_repository_stage() -> None:
    root = _repo_root()
    make_recipes = _all_recipes(root)
    candidate, _ = _require_recipe_text(make_recipes, "finalization-check-target")
    canonical, _ = _require_recipe_text(make_recipes, "finalization-check")
    assert candidate is not None and canonical is not None

    phase6 = _validator_gate_invocations(
        candidate, script="scripts/validate_refactor_phase_6.py"
    )
    assert len(phase6) == 1
    assert phase6[0].arguments == ("--stage", "pre-cutover")

    assert "validate-schemas" not in candidate
    assert "probe-console-deterministic" not in candidate

    assert "$(MAKE) validate-schemas" in canonical
    assert "$(MAKE) probe-console-deterministic" in canonical
    assert "--stage cutover" not in canonical
    assert "--final" not in canonical


def test_cutover_requires_jung_runtime_and_target_gate(tmp_path: Path) -> None:
    _write_pre_cutover_tree(tmp_path)
    (tmp_path / "docker-compose.yml").write_text(
        textwrap.dedent(
            """
            networks:
              app-network:
                driver: bridge
            services:
              api:
                image: jung-local:dev
                build:
                  context: .
                  dockerfile: Dockerfile
                  target: development
                user: "${HOST_UID:-1000}:${HOST_GID:-1000}"
                command: jung-api
                ports:
                  - "127.0.0.1:8000:8000"
                healthcheck:
                  test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8000/api/v1/health"]
                environment:
                  JUNG_DATA_DIR: "${JUNG_DATA_DIR:-/app/data/default}"
                  JUNG_API_HOST: "0.0.0.0"
                  JUNG_API_ALLOW_REMOTE_BIND: "true"
                volumes:
                  - ./data:/app/data
                networks:
                  - app-network
              console:
                image: jung-local:dev
                profiles: ["console"]
                stdin_open: true
                tty: true
                command:
                  - jung-console
                  - --api-url
                  - http://api:8000
                networks:
                  - app-network
              db-viewer:
                image: coleifer/sqlite-web
                profiles: ["debug"]
                volumes:
                  - ./data:/data:ro
                ports:
                  - "127.0.0.1:8080:8080"
                command:
                  - sqlite_web
                  - --host
                  - "0.0.0.0"
                  - --port
                  - "8080"
                  - "/data/${DB_FILE:-default/jung.db}"
            """
        ).lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "Dockerfile").write_text(
        textwrap.dedent(
            """
            FROM python:3.11-slim AS development
            CMD ["jung-api"]
            """
        ).lstrip(),
        encoding="utf-8",
    )
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
    (tmp_path / ".env.example").write_text(
        "# JUNG_DATA_DIR=/app/data/default\n",
        encoding="utf-8",
    )
    (tmp_path / "Makefile").write_text(
        _makefile_preamble().replace(
            ".PHONY: finalization-check finalization-check-target test-target \\\n"
            "\tprobe-console-v1-deterministic validate-refactor-phase-6",
            ".PHONY: finalization-check finalization-check-target test-target \\\n"
            "\tprobe-console-v1-deterministic validate-refactor-phase-6 run-server \\\n"
            "\tui-console ui-console-test docker-db-view docker-db-backup \\\n"
            "\tdocker-db-backup-verify docker-db-restore reset-jung-db \\\n"
            "\treset-manual-test smoke-target-local-llm dev-install",
        )
        + textwrap.dedent(
            """
            JUNG_DB_PROFILE ?= default
            ifneq ($(JUNG_DB_PROFILE),default)
            ifneq ($(JUNG_DB_PROFILE),manual-test)
            $(error JUNG_DB_PROFILE must be default or manual-test)
            endif
            endif
            JUNG_DB_DATA_DIR := /app/data/$(JUNG_DB_PROFILE)
            JUNG_DB_RELATIVE_FILE := $(JUNG_DB_PROFILE)/jung.db

            run-server:
            \tdocker compose up --build --remove-orphans api

            dev-install:
            \tdocker compose build api

            ui-console:
            \tJUNG_DATA_DIR=/app/data/default docker compose up -d --wait api
            \tJUNG_DATA_DIR=/app/data/default docker compose --profile console run --rm -it --no-deps console

            ui-console-test:
            \tdocker compose down --remove-orphans
            \tJUNG_DATA_DIR=/app/data/manual-test docker compose up -d --wait api
            \tJUNG_DATA_DIR=/app/data/manual-test docker compose --profile console run --rm -it --no-deps console

            docker-db-backup:
            \tJUNG_DATA_DIR=$(JUNG_DB_DATA_DIR) docker compose run --rm --no-deps api jung-db backup

            docker-db-backup-verify:
            \t@test -n "$(BACKUP)" || { echo "BACKUP is required"; exit 2; }
            \tdocker compose run --rm --no-deps api jung-db verify "$(BACKUP)"

            docker-db-restore:
            \t@test -n "$(BACKUP)" || { echo "BACKUP is required"; exit 2; }
            \tdocker compose stop api
            \tJUNG_DATA_DIR=$(JUNG_DB_DATA_DIR) docker compose run --rm --no-deps api jung-db restore "$(BACKUP)" --replace

            docker-db-view:
            \tDB_FILE=$(JUNG_DB_RELATIVE_FILE) docker compose --profile debug up --remove-orphans db-viewer

            reset-jung-db:
            \tdocker compose stop api
            \trm -f data/default/jung.db data/default/jung.db-wal data/default/jung.db-shm

            reset-manual-test:
            \tdocker compose stop api
            \trm -f data/manual-test/jung.db data/manual-test/jung.db-wal data/manual-test/jung.db-shm

            help:
            \t@echo ui-console ui-console-test docker-db-view reset-jung-db reset-manual-test smoke-target-local-llm
            """
        ).lstrip()
        + _test_target_recipe()
        + "\n"
        + textwrap.dedent(
            """
            finalization-check: prepare-runtime-dirs
            \t$(MAKE) lint
            \t$(MAKE) validate-docs
            \t$(MAKE) test-target
            \tdocker compose --profile test run --rm test python scripts/validate_refactor_phase_6.py --stage cutover
            \tdocker compose --profile test run --rm test python scripts/validate_refactor_phase_5.py
            \t$(MAKE) probe-console-v1-deterministic
            """
        ).lstrip(),
        encoding="utf-8",
    )
    errors = validate(tmp_path, stage="cutover")
    assert errors == []
